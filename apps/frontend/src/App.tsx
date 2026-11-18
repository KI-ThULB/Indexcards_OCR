import { MainLayout } from './layouts/MainLayout';
import { useWizardStore } from './store/wizardStore';
import { UploadStep } from './features/upload/UploadStep';
import { ConfigureStep } from './features/configure/ConfigureStep';
import { ProcessingStep } from './features/processing/ProcessingStep';
import { ResultsStep } from './features/results/ResultsStep';
import { VerifyStep } from './features/verify/VerifyStep';
import { BatchHistoryDashboard } from './features/history/BatchHistoryDashboard';
import { CleanStep } from './features/clean/CleanStep';
import { BulkView } from './features/bulk/BulkView';

function App() {
  const batchRevision = useWizardStore((state) => state.batchRevision);
  const step = useWizardStore((state) => state.step);
  const view = useWizardStore((state) => state.view);

  const renderContent = () => {
    if (view === 'history') {
      return <BatchHistoryDashboard />;
    }

    if (view === 'bulk') {
      return <BulkView />;
    }

    switch (step) {
      case 'upload':
        return <UploadStep />;
      case 'configure':
        return <ConfigureStep />;
      case 'processing':
        return <ProcessingStep key={batchRevision} />;
      case 'results':
        return <ResultsStep key={batchRevision} />;
      case 'verify':
        return <VerifyStep key={batchRevision} />;
      case 'clean':
        return <CleanStep key={batchRevision} />;
      default:
        return null;
    }
  };

  return (
    <MainLayout>
      <div className="space-y-6">
        {renderContent()}
      </div>
    </MainLayout>
  );
}

export default App;
